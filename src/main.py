import numpy as np
import torch
from sklearn.linear_model import LinearRegression
import time

import numpy as np
import scipy
from scipy.spatial.distance import pdist
from scipy.spatial.distance import squareform



def sim_data(beta:np.ndarray, theta:np.ndarray, sigma2:float, W:np.ndarray, Q:np.ndarray, Q_f:np.ndarray, d: np.ndarray, d_f:np.ndarray, Iw:bool, T:int, X:np.ndarray = None) -> (np.ndarray,np.ndarray):
    """
      Function for simulating data



      Parameters
      ----------
      Q: ndarray
            the matrix formed by eigenvectors of small w, which has dimension n_1D**2 x n_1D**2

      d: ndarray
            the vector containing all the eigenvalues of small w, which has dimension n_1D**2
      Iw: bool
            if true, the spatial weight matrix W will take kron product from small w
      X: ndarray
            if X is given, then use X to generate Y, and will return unchanged X and simulated Y


      Returns
      -------
      simulated X and Y


      Raises
      ------
      ValueError

      """

    Lambda = theta[0]
    gamma = theta[1]
    rho = theta[2]
    sigma = np.sqrt(sigma2)
    n = W.shape[0]
    k = len(beta)

    if X is None:
        X = np.hstack((np.ones([n*T,1]), np.random.normal(0,sigma,[n*T,1])))
        #X = np.hstack((np.ones([n*T,1]), 0.5*np.ones([n*T,1])))


    Y = np.zeros([n*T,1])
    U = np.zeros([n*T,1])
    #V = 0.1*np.ones([n*T,1])
    V = np.random.normal(0,sigma,[n*T,1])

    if Iw:
        nw = Q.shape[0]
        R = np.kron(np.identity(np.int(n/nw)), Q @ np.diag(rho*d+gamma) @ Q.transpose())
        S_inv = np.kron(np.identity(np.int(n/nw)),Q @ np.diag(1/(1-Lambda*(d))) @ Q.transpose())
    else:
        # R = Q_f @ np.diag(rho*d_f + gamma) @ Q_f.transpose()
        # S_inv = Q_f @ np.diag(1/(1-Lambda*d_f)) @ Q_f.transpose()
        # use hard inverse
        R = rho*W + gamma*np.identity(n)
        S_inv = np.linalg.inv(np.identity(n)-Lambda*W)

    V0 = np.random.normal(0,sigma,[n,1])
    #V0 = 0.2*np.ones([n,1])
    U0 = S_inv @ V0
    U[:n] = S_inv @ (R @ U0 + V[:n])

    for t in range(2,T+1):
        U[(t-1)*n:n*t] = S_inv @ (R @ U[(t-2)*n:(t-1)*n] + V[(t-1)*n:n*t])

    # debug


    Y = X @ beta + U.flatten()





    return X,Y




def gen_W_exp(n_1D:int, cutoff:float) -> np.ndarray:
    """
       generate small weight matrix, return a n_1D**2 x n_1D**2 matrix


       Parameters
       ----------


       Returns
       -------
        W: ndarray:
            a small spatial weight matrix of dimension n_1D**2 x n_1D**2

       Raises
       ------
       ValueError

       """
    coord = np.hstack((np.kron(np.arange(1,n_1D+1).reshape(n_1D,1),np.ones([n_1D,1])), np.kron(np.ones([n_1D,1]), np.arange(1,n_1D+1).reshape(n_1D,1))))

    N = n_1D**2

    W = np.exp(-squareform(pdist(coord))) * (np.ones([N,N]) - np.identity(N))

    W = W * (W <= cutoff)

    return W



def gen_W_blk(n_1D: int, W_diag: np.ndarray, sparse=False) -> np.ndarray:
    """
           generate block diagonal matrix, let N = n_1D x n_1D, return a N x N weight matrix


           Parameters
           ----------
           n_1D: int
                we have N = n_1D x n_1D

           W_diag: ndarray
                 small spatial weight matrix
           Returns
           -------
           W: ndarray
                 A block spatial weight matrix NxN array generated by w kronproduct Ip

           Raises
           ------
           ValueError

    """

    N = n_1D ** 2
    n_W = W_diag.shape[0]
    if sparse:
        p = np.int(N / n_W)
        a = scipy.sparse.coo_matrix((np.ones(p),(np.arange(p), np.arange(p))), shape=(p, p))

        W = scipy.sparse.kron(a, W_diag).tocoo()


    else:
        W = np.kron(np.identity(np.int(N / n_W)), W_diag)
        W = W[:N, :N]

    return W



def nloglik_banded(para, Y, X, W, Q, d, n_iter):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    beta, theta = np.split(para, [-3])

    beta = torch.tensor(beta, requires_grad=True, dtype=torch.float32, device=device)
    theta = torch.tensor(theta, requires_grad=True, dtype=torch.float32, device=device)

    print(beta.is_leaf)
    print(theta.is_leaf)
    k = len(para) - 3

    Lambda = theta[0]
    gamma = theta[1]
    rho = theta[2]

    optimizer = torch.optim.Adam([beta, theta], lr=1e-1)

    Y = torch.from_numpy(Y).to(device)
    X = torch.from_numpy(X).to(device)
    X, Y = X.type(torch.float32), Y.type(torch.float32)



    Q = torch.from_numpy(Q).to(device)
    d = torch.from_numpy(d).to(device)

    values = W.data
    indices = np.vstack((W.row, W.col))

    i = torch.LongTensor(indices).to(device)
    v = torch.FloatTensor(values).to(device)
    shape = W.shape

    W = torch.sparse.FloatTensor(i, v, torch.Size(shape)).to(device)



    N = W.size(0)
    T = np.int(Y.size(0) / N)
    NT = N * T


    constant = (np.log(2 * np.pi) - np.log(N) - np.log(T) + 1) / 2



    n = Q.size(0)
    p = N / n
    I_N = torch.sparse_coo_tensor(indices=torch.stack([torch.arange(N), torch.arange(N)]), values=torch.ones(N),
                            size=[N, N]).to(device)




    for iter in range(n_iter):

        print('iter %d'%iter)

        U = Y - X @ beta


        temp1 = torch.sparse.FloatTensor(i, v * rho, torch.Size(shape)).to(device)

        temp2 = torch.sparse_coo_tensor(indices=torch.stack([torch.arange(N, device=device), torch.arange(N, device=device)]), values=torch.ones(N, device=device) * gamma,
                                size=[N, N]).to(device)

        R = temp1 + temp2
        temp3 = torch.sparse.FloatTensor(i, v * Lambda, torch.Size(shape)).to(device)
        #S = I_N - Lambda * W
        S = I_N - temp3
        #R2 = R @ R
        R2 = torch.sparse.mm(R, R)
        #S2 = S @ S
        S2 = torch.sparse.mm(S, S)

        #RS = R @ S
        RS = torch.sparse.mm(R, S)
        # A, _ =  torch.solve(R.to_dense(), S.to_dense())
        #
        # A2 = A @ A
        #
        #
        # K_inv = - A2 + I_N

        SKinvS = S2 - R2

        U_2_T = U[N:].reshape([T-1, N]).transpose(0, 1)
        #U_2_T_minus1 = U[N:(NT-N)].reshape([T-2, N]).transpose(0, 1)

        U_1_T_minus1 = U[:(NT-N)].reshape([T-1, N]).transpose(0, 1)
        U_1_T = U.reshape([T, N]).transpose(0, 1)

        #SKinvS_U_1 = SKinvS @ U_1_T_minus1[:,0]
        SKinvS_U_1 = torch.sparse.mm(SKinvS, U_1_T_minus1[:,0][:,None])
        #S2_U_2T = S2 @ U_2_T
        S2_U_2T = torch.sparse.mm(S2, U_2_T)
        #R2_U_1T_minus1 = R2@U_1_T_minus1
        R2_U_1T_minus1 = torch.sparse.mm(R2, U_1_T_minus1[:,0][:,None])

        #RS_U_2T = RS @ U_2_T
        RS_U_2T = torch.sparse.mm(RS, U_2_T)


        ell_SKS = U_1_T_minus1[:,0] @ SKinvS_U_1
        ell_S2 = torch.sum(torch.diag(U_2_T.transpose(0, 1) @ S2_U_2T))
        ell_R2 = torch.sum(torch.diag(U_1_T_minus1.transpose(0, 1) @ R2_U_1T_minus1))
        ell_RS = -2 * torch.sum(torch.diag(U_1_T_minus1.transpose(0, 1) @ RS_U_2T))

        H = ell_SKS + ell_S2 + ell_R2 + ell_RS

        #log_det_K = -torch.logdet(K_inv)
        log_det_S = torch.logdet(S.to_dense())
        log_det_K = 2 * log_det_S - torch.logdet((S2-R2).to_dense())
        print('log_det_K is %.4f'%log_det_K)



        print('log_det_S is %.4f'%log_det_S)


        f_value = torch.log(H) / 2 + 0.5 * log_det_K / NT - log_det_S / N + constant
        print("f value is %.4f"%f_value.item())



        optimizer.zero_grad()

        f_value.backward(retain_graph=True)
        print('grad:')
        print(beta.grad)
        print(theta.grad)

        optimizer.step()

        print('beta:')
        print(beta)
        print('theta:')
        print(theta)






if __name__ == '__main__':
    n = 160
    T = 5
    n_diag = 5
    sigma2 = 0.5
    beta = np.array([1, 0.5])
    theta = np.array([0.1, 0.1, -0.1])

    W_diag = gen_W_exp(n_diag, np.inf)

    d, Q = np.linalg.eig(W_diag)
    idx = np.argsort(d)
    d = d[idx]
    Q = Q[:, idx]

    W = gen_W_blk(n, W_diag, sparse=True)



    sim_X, sim_Y = sim_data(beta, theta, sigma2, W, Q, None, d, None, False, T)

    beta_hat_ols = LinearRegression(fit_intercept=False).fit(sim_X, sim_Y).coef_

    beta_hat_ols = [0.7, 0.3]
    theta_init = np.array([0., 0., 0.])

    para_init = np.concatenate([beta_hat_ols, theta_init])

    start_time = time.time()
    n_iter = 10
    nloglik_banded(para_init, sim_Y, sim_X, W, Q, d, n_iter)
    time_elapsed = time.time() - start_time
    print("After %d iterations, the elapsed time is %.4f" % (n_iter, time_elapsed))
